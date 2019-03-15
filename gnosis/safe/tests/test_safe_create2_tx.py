import logging

from django.test import TestCase
from eth_account import Account

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.contracts import get_safe_contract
from gnosis.eth.utils import get_eth_address_with_key

from ..safe_create2_tx import SafeCreate2TxBuilder
from .test_safe_service import SafeTestCaseMixin
from .utils import generate_salt_nonce

logger = logging.getLogger(__name__)

LOG_TITLE_WIDTH = 100


class TestSafeCreationTx(TestCase, SafeTestCaseMixin):
    @classmethod
    def setUpTestData(cls):
        cls.prepare_tests()

    def test_safe_create2_tx_builder(self):
        w3 = self.w3

        salt_nonce = generate_salt_nonce()
        funder_account = self.ethereum_test_account
        owners = [Account.create().address for _ in range(4)]
        threshold = len(owners) - 1
        gas_price = self.gas_price

        safe_creation_tx = SafeCreate2TxBuilder(w3=w3,
                                                master_copy_address=self.safe_contract_address,
                                                proxy_factory_address=self.proxy_factory_contract_address
                                                ).build(owners=owners,
                                                        threshold=threshold,
                                                        salt_nonce=salt_nonce,
                                                        gas_price=gas_price)

        self.assertEqual(safe_creation_tx.payment, safe_creation_tx.payment_ether)
        self.send_tx({
            'to': safe_creation_tx.safe_address,
            'value': safe_creation_tx.payment,
        }, funder_account)

        funder_pkey = funder_account.privateKey
        tx_hash, contract_address = self.safe_service.deploy_proxy_contract_with_nonce(salt_nonce,
                                                                                       safe_creation_tx.safe_setup_data,
                                                                                       safe_creation_tx.gas,
                                                                                       safe_creation_tx.gas_price,
                                                                                       deployer_private_key=funder_pkey)
        tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
        self.assertEqual(tx_receipt.status, 1)
        logs = self.proxy_factory_contract.events.ProxyCreation().processReceipt(tx_receipt)
        log = logs[0]
        self.assertIsNone(tx_receipt.contractAddress)
        self.assertEqual(log['event'], 'ProxyCreation')
        proxy_address = log['args']['proxy']
        self.assertEqual(proxy_address, safe_creation_tx.safe_address)
        self.assertEqual(contract_address, safe_creation_tx.safe_address)

        deployed_safe_proxy_contract = get_safe_contract(w3, proxy_address)
        self.assertEqual(deployed_safe_proxy_contract.functions.getThreshold().call(), threshold)
        self.assertEqual(deployed_safe_proxy_contract.functions.getOwners().call(), owners)
        self.assertEqual(self.ethereum_service.get_balance(proxy_address), 0)

    def test_safe_create2_tx_builder_with_fixed_cost(self):
        w3 = self.w3

        salt_nonce = generate_salt_nonce()
        funder_account = self.ethereum_test_account
        owners = [Account.create().address for _ in range(4)]
        threshold = len(owners) - 1
        gas_price = self.gas_price
        fixed_creation_cost = 123  # Wei

        safe_creation_tx = SafeCreate2TxBuilder(w3=w3,
                                                master_copy_address=self.safe_contract_address,
                                                proxy_factory_address=self.proxy_factory_contract_address
                                                ).build(owners=owners,
                                                        threshold=threshold,
                                                        salt_nonce=salt_nonce,
                                                        gas_price=gas_price,
                                                        fixed_creation_cost=fixed_creation_cost)

        self.assertEqual(safe_creation_tx.payment, fixed_creation_cost)
        self.assertEqual(safe_creation_tx.payment_ether, safe_creation_tx.gas * safe_creation_tx.gas_price)

        self.send_tx({
            'to': safe_creation_tx.safe_address,
            'value': safe_creation_tx.payment,
        }, funder_account)

        funder_pkey = funder_account.privateKey
        tx_hash, contract_address = self.safe_service.deploy_proxy_contract_with_nonce(salt_nonce,
                                                                                       safe_creation_tx.safe_setup_data,
                                                                                       safe_creation_tx.gas,
                                                                                       safe_creation_tx.gas_price,
                                                                                       deployer_private_key=funder_pkey)
        tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
        self.assertEqual(tx_receipt.status, 1)
        logs = self.proxy_factory_contract.events.ProxyCreation().processReceipt(tx_receipt)
        log = logs[0]
        self.assertIsNone(tx_receipt.contractAddress)
        self.assertEqual(log['event'], 'ProxyCreation')
        proxy_address = log['args']['proxy']
        self.assertEqual(proxy_address, safe_creation_tx.safe_address)
        self.assertEqual(contract_address, safe_creation_tx.safe_address)

        deployed_safe_proxy_contract = get_safe_contract(w3, proxy_address)
        self.assertEqual(deployed_safe_proxy_contract.functions.getThreshold().call(), threshold)
        self.assertEqual(deployed_safe_proxy_contract.functions.getOwners().call(), owners)
        self.assertEqual(self.ethereum_service.get_balance(proxy_address), 0)

    def test_safe_create2_tx_builder_with_token_payment(self):
        w3 = self.w3

        salt_nonce = generate_salt_nonce()
        erc20_deployer = Account.create()
        funder_account = self.ethereum_test_account
        owners = [Account.create().address for _ in range(4)]
        threshold = len(owners) - 1
        gas_price = self.gas_price
        token_amount = int(1e18)
        erc20_contract = self.deploy_example_erc20(token_amount, erc20_deployer.address)
        self.assertEqual(erc20_contract.functions.balanceOf(erc20_deployer.address).call(), token_amount)

        # Send something to the erc20 deployer
        self.send_tx({
            'to': erc20_deployer.address,
            'value': w3.toWei(1, 'ether')
        }, funder_account)

        safe_creation_tx = SafeCreate2TxBuilder(w3=w3,
                                                master_copy_address=self.safe_contract_address,
                                                proxy_factory_address=self.proxy_factory_contract_address
                                                ).build(owners=owners,
                                                        threshold=threshold,
                                                        salt_nonce=salt_nonce,
                                                        gas_price=gas_price,
                                                        payment_token=erc20_contract.address)

        self.assertEqual(safe_creation_tx.payment_token, erc20_contract.address)
        self.assertGreater(safe_creation_tx.payment, 0)
        self.assertEqual(safe_creation_tx.payment_ether, safe_creation_tx.gas * safe_creation_tx.gas_price)

        self.send_tx(erc20_contract.functions.transfer(safe_creation_tx.safe_address,
                                                       safe_creation_tx.payment).buildTransaction({'from': erc20_deployer.address}),
                     erc20_deployer)
        self.assertEqual(erc20_contract.functions.balanceOf(safe_creation_tx.safe_address).call(),
                         safe_creation_tx.payment)

        funder_pkey = funder_account.privateKey
        tx_hash, contract_address = self.safe_service.deploy_proxy_contract_with_nonce(salt_nonce,
                                                                                       safe_creation_tx.safe_setup_data,
                                                                                       safe_creation_tx.gas,
                                                                                       safe_creation_tx.gas_price,
                                                                                       deployer_private_key=funder_pkey)
        tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
        self.assertEqual(tx_receipt.status, 1)
        logs = self.proxy_factory_contract.events.ProxyCreation().processReceipt(tx_receipt)
        log = logs[0]
        self.assertIsNone(tx_receipt.contractAddress)
        self.assertEqual(log['event'], 'ProxyCreation')
        proxy_address = log['args']['proxy']
        self.assertEqual(proxy_address, safe_creation_tx.safe_address)
        self.assertEqual(contract_address, safe_creation_tx.safe_address)

        deployed_safe_proxy_contract = get_safe_contract(w3, proxy_address)
        self.assertEqual(deployed_safe_proxy_contract.functions.getThreshold().call(), threshold)
        self.assertEqual(deployed_safe_proxy_contract.functions.getOwners().call(), owners)
        self.assertEqual(self.ethereum_service.get_balance(proxy_address), 0)

    def test_safe_gas_with_multiple_owners(self):
        logger.info("Test Safe Proxy create2 gas with multiple owners".center(LOG_TITLE_WIDTH, '-'))
        w3 = self.w3
        funder_account = self.ethereum_test_account
        number_of_accounts = 10
        for i in range(2, number_of_accounts):
            salt_nonce = generate_salt_nonce()
            owners = [Account.create().address for _ in range(i + 1)]
            threshold = len(owners) - 1
            gas_price = self.gas_price

            safe_creation_tx = SafeCreate2TxBuilder(w3=w3,
                                                    master_copy_address=self.safe_contract_address,
                                                    proxy_factory_address=self.proxy_factory_contract_address
                                                    ).build(owners=owners,
                                                            threshold=threshold,
                                                            salt_nonce=salt_nonce,
                                                            gas_price=gas_price)

            self.send_tx({
                'to': safe_creation_tx.safe_address,
                'value': safe_creation_tx.payment,
            }, funder_account)

            funder_pkey = funder_account.privateKey
            tx_hash, contract_address = self.safe_service.deploy_proxy_contract_with_nonce(salt_nonce,
                                                                                           safe_creation_tx.safe_setup_data,
                                                                                           safe_creation_tx.gas,
                                                                                           safe_creation_tx.gas_price,
                                                                                           deployer_private_key=funder_pkey)
            tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
            self.assertEqual(tx_receipt.status, 1)
            logs = self.proxy_factory_contract.events.ProxyCreation().processReceipt(tx_receipt)
            log = logs[0]
            self.assertIsNone(tx_receipt.contractAddress)
            self.assertEqual(log['event'], 'ProxyCreation')
            proxy_address = log['args']['proxy']
            self.assertEqual(proxy_address, safe_creation_tx.safe_address)
            self.assertEqual(contract_address, safe_creation_tx.safe_address)

            logger.info("Number of owners: %d - Gas estimated %d - Gas Used %d - Difference %d - Gas used per owner %d",
                        len(owners),
                        safe_creation_tx.gas,
                        tx_receipt.gasUsed,
                        safe_creation_tx.gas - tx_receipt.gasUsed,
                        tx_receipt.gasUsed // len(owners))