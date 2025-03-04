import secrets
from abc import ABCMeta
from typing import Callable, Optional

from eth_account.signers.local import LocalAccount
from eth_typing import ChecksumAddress
from web3 import Web3
from web3.contract.contract import Contract, ContractFunction

from gnosis.eth import EthereumClient, EthereumTxSent
from gnosis.eth.contracts import (
    ContractBase,
    get_paying_proxy_deployed_bytecode,
    get_proxy_1_0_0_deployed_bytecode,
    get_proxy_1_1_1_deployed_bytecode,
    get_proxy_1_1_1_mainnet_deployed_bytecode,
    get_proxy_1_3_0_deployed_bytecode,
    get_proxy_1_4_1_deployed_bytecode,
    get_proxy_factory_V1_0_0_contract,
    get_proxy_factory_V1_1_1_contract,
    get_proxy_factory_V1_3_0_contract,
    get_proxy_factory_V1_4_1_contract,
)
from gnosis.eth.utils import compare_byte_code, get_empty_tx_params
from gnosis.util import cache


class ProxyFactory(ContractBase, metaclass=ABCMeta):
    def __new__(cls, *args, version: str = "1.4.1", **kwargs) -> "ProxyFactory":
        versions = {
            "1.0.0": ProxyFactoryV100,
            "1.1.1": ProxyFactoryV111,
            "1.3.0": ProxyFactoryV130,
            "1.4.1": ProxyFactoryV141,
        }
        instance_class = versions[version]
        instance = super().__new__(instance_class)
        return instance

    @classmethod
    def deploy_contract(
        cls, ethereum_client: EthereumClient, deployer_account: LocalAccount
    ) -> EthereumTxSent:
        """
        Deploy Proxy Factory contract

        :param ethereum_client:
        :param deployer_account: Ethereum Account
        :return: ``EthereumTxSent`` with the deployed contract address
        """
        contract_fn = cls.get_contract_fn(cls)
        contract = contract_fn(ethereum_client.w3)
        constructor_data = contract.constructor().build_transaction(
            get_empty_tx_params()
        )["data"]
        return ethereum_client.deploy_and_initialize_contract(
            deployer_account, constructor_data
        )

    def check_proxy_code(self, address: ChecksumAddress) -> bool:
        """
        Check if proxy bytecode matches any of the deployed by the supported Proxy Factories

        :param address: Ethereum address to check
        :return: ``True`` if proxy is valid, ``False`` otherwise
        """

        deployed_proxy_code = self.w3.eth.get_code(address)
        proxy_code_fns = (
            get_proxy_1_4_1_deployed_bytecode,
            get_proxy_1_3_0_deployed_bytecode,
            get_proxy_1_1_1_deployed_bytecode,
            get_proxy_1_1_1_mainnet_deployed_bytecode,
            get_proxy_1_0_0_deployed_bytecode,
            get_paying_proxy_deployed_bytecode,
            self.get_proxy_runtime_code,
        )
        for proxy_code_fn in proxy_code_fns:
            proxy_code = proxy_code_fn()
            if proxy_code and compare_byte_code(deployed_proxy_code, proxy_code):
                return True
        return False

    def _deploy_proxy_contract(
        self,
        deployer_account: LocalAccount,
        deploy_fn: ContractFunction,
        gas: Optional[int] = None,
        gas_price: Optional[int] = None,
        nonce: Optional[int] = None,
    ) -> EthereumTxSent:
        """
        Common logic for `createProxy` and `createProxyWithNonce`

        :param deployer_account:
        :param deploy_fn:
        :param gas:
        :param gas_price:
        :param nonce:
        :return: EthereumTxSent
        """

        tx_params = self.ethereum_client.build_tx_params(
            from_address=deployer_account.address,
            gas=gas,
            gas_price=gas_price,
            nonce=nonce,
        )
        contract_address = deploy_fn.call(tx_params)
        tx = deploy_fn.build_transaction(tx_params)
        tx_hash = self.ethereum_client.send_unsigned_transaction(
            tx, private_key=deployer_account.key
        )

        return EthereumTxSent(tx_hash, tx, contract_address)

    def deploy_proxy_contract(
        self,
        deployer_account: LocalAccount,
        master_copy: ChecksumAddress,
        initializer: bytes = b"",
        gas: Optional[int] = None,
        gas_price: Optional[int] = None,
        nonce: Optional[int] = None,
    ) -> EthereumTxSent:
        """
        Deploy proxy contract via ProxyFactory using `createProxy` function (CREATE opcode)

        :param deployer_account: Ethereum account
        :param master_copy: Address the proxy will point at
        :param initializer: Initializer for the deployed proxy
        :param gas: Gas
        :param gas_price: Gas Price
        :param nonce: Nonce
        :return: EthereumTxSent
        """
        create_proxy_fn = self.contract.functions.createProxy(master_copy, initializer)

        return self._deploy_proxy_contract(
            deployer_account, create_proxy_fn, gas=gas, gas_price=gas_price, nonce=nonce
        )

    def deploy_proxy_contract_with_nonce(
        self,
        deployer_account: LocalAccount,
        master_copy: ChecksumAddress,
        initializer: bytes = b"",
        salt_nonce: Optional[int] = None,
        gas: Optional[int] = None,
        gas_price: Optional[int] = None,
        nonce: Optional[int] = None,
    ) -> EthereumTxSent:
        """
        Deploy proxy contract via Proxy Factory using `createProxyWithNonce` (CREATE2 opcode)

        :param deployer_account: Ethereum account
        :param master_copy: Address the proxy will point at
        :param initializer: Initializer for the deployed proxy
        :param salt_nonce: Uint256 for ``CREATE2`` salt. If not provided, a random one will be used
        :param gas: Gas
        :param gas_price: Gas Price
        :param nonce: Nonce
        :return: EthereumTxSent
        """
        salt_nonce = salt_nonce if salt_nonce is not None else secrets.randbits(256)
        create_proxy_fn = self.contract.functions.createProxyWithNonce(
            master_copy, initializer, salt_nonce
        )

        return self._deploy_proxy_contract(
            deployer_account, create_proxy_fn, gas=gas, gas_price=gas_price, nonce=nonce
        )

    @cache
    def get_proxy_runtime_code(self) -> Optional[bytes]:
        """
        :return: Runtime code for current proxy factory. For v1.4.1 onwards the method is not avaiable, so `None`
            will be returned
        """
        if hasattr(self.contract.functions, "proxyRuntimeCode"):
            return self.contract.functions.proxyRuntimeCode().call()


class ProxyFactoryV100(ProxyFactory):
    def get_contract_fn(self) -> Callable[[Web3, ChecksumAddress], Contract]:
        return get_proxy_factory_V1_0_0_contract


class ProxyFactoryV111(ProxyFactory):
    def get_contract_fn(self) -> Callable[[Web3, ChecksumAddress], Contract]:
        return get_proxy_factory_V1_1_1_contract


class ProxyFactoryV130(ProxyFactory):
    def get_contract_fn(self) -> Callable[[Web3, ChecksumAddress], Contract]:
        return get_proxy_factory_V1_3_0_contract


class ProxyFactoryV141(ProxyFactory):
    def get_contract_fn(self) -> Callable[[Web3, ChecksumAddress], Contract]:
        return get_proxy_factory_V1_4_1_contract

    def deploy_proxy_contract(self, *args, **kwargs):
        """
        .. deprecated:: ``createProxy`` function was deprecated in v1.4.1, use ``deploy_proxy_contract_with_nonce``

        :param args:
        :param kwargs:
        :return:
        """
        raise NotImplementedError("Deprecated, use `deploy_proxy_contract_with_nonce`")
