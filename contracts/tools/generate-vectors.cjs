// Independent JavaScript EIP-712 oracle. Fixture identity 7 is public test data.
const { Wallet, utils } = require('ethers');
const fs = require('node:fs');
const path = require('node:path');
const fields = [
  ['requestId', 'bytes32'], ['invoiceHash', 'bytes32'], ['fingerprint', 'bytes32'],
  ['treasury', 'address'], ['payingWallet', 'address'], ['asset', 'address'], ['payee', 'address'],
  ['amount', 'uint256'], ['earlyAmount', 'uint256'], ['earlyPayBy', 'uint64'],
  ['deadline', 'uint64'], ['termsHash', 'bytes32'], ['expiry', 'uint64'],
].map(([name, type]) => ({ name, type }));
const types = { PaymentApproval: fields };
const domain = {
  name: 'TreasuryPilot', version: '1', chainId: 11155111,
  verifyingContract: '0x111122223333444455556666777788889999aaaa',
};
const base = {
  requestId: utils.id('synthetic-request-1'), invoiceHash: utils.id('synthetic-invoice-1'),
  fingerprint: utils.id('synthetic-fingerprint-1'), treasury: domain.verifyingContract,
  payingWallet: '0x22223333444455556666777788889999aaaabbbb',
  asset: '0x94a9d9ac8a22534e3faca9f4e7f2e2cf85d5e4c8',
  payee: '0x3333444455556666777788889999aaaabbbbcccc',
  amount: '100000000', earlyAmount: '0', earlyPayBy: 0,
  deadline: 1800000000, termsHash: utils.id('synthetic-terms-1'), expiry: 1801209600,
};
const typeText = `PaymentApproval(${fields.map(f => `${f.type} ${f.name}`).join(',')})`;
async function generate() {
  const wallet = new Wallet(utils.hexZeroPad(utils.hexlify(7), 32));
  for (const [file, changes] of [
    ['payment-approval.json', {}],
    ['payment-approval-early.json', { earlyAmount: '90000000', earlyPayBy: 1799990000 }],
    ['payment-approval-large.json', { amount: '9007199254740993000000' }],
  ]) {
    const message = { ...base, ...changes };
    const signature = await wallet._signTypedData(domain, types, message);
    const result = {
      formatVersion: 1, generator: 'ethers@5.4.0', fixtureIdentity: 7,
      domain, types, message, typeHash: utils.id(typeText),
      structHash: utils._TypedDataEncoder.hashStruct('PaymentApproval', types, message),
      domainSeparator: utils._TypedDataEncoder.hashDomain(domain),
      digest: utils._TypedDataEncoder.hash(domain, types, message),
      signer: wallet.address, signature,
      approverSig: utils.defaultAbiCoder.encode(['address', 'bytes'], [wallet.address, signature]),
    };
    fs.writeFileSync(path.join(__dirname, '../test/vectors', file), JSON.stringify(result, null, 2) + '\n');
  }
  const policyDomain = { ...domain, name: 'TreasuryPilot Policy' };
  const policyFields = [
    ['planHash', 'bytes32'], ['requestId', 'bytes32'], ['stepIds', 'bytes32[]'],
    ['policyVersion', 'bytes32'], ['executor', 'address'], ['validUntil', 'uint64'],
    ['nonce', 'uint256'], ['evidenceDigest', 'bytes32'],
  ].map(([name, type]) => ({ name, type }));
  const policyTypes = { PlanAttestation: policyFields };
  const policyTypeText = `PlanAttestation(${policyFields.map(f => `${f.type} ${f.name}`).join(',')})`;
  const policyWallet = new Wallet(utils.hexZeroPad(utils.hexlify(8), 32)); // public fixture
  for (const [file, stepIds] of [
    ['plan-attestation.json', [utils.id('synthetic-refill-step'), utils.id('synthetic-pay-step')]],
    ['plan-attestation-empty.json', []],
  ]) {
    const message = {
      planHash: utils.id('synthetic-canonical-plan'), requestId: base.requestId, stepIds,
      policyVersion: utils.id('synthetic-policy-v1'), executor: base.payingWallet,
      validUntil: 1800000900, nonce: '340282366920938463463374607431768211455',
      evidenceDigest: utils.id('synthetic-evidence'),
    };
    const result = {
      formatVersion: 1, generator: 'ethers@5.4.0', fixtureIdentity: 8,
      domain: policyDomain, types: policyTypes, message, typeHash: utils.id(policyTypeText),
      structHash: utils._TypedDataEncoder.hashStruct('PlanAttestation', policyTypes, message),
      domainSeparator: utils._TypedDataEncoder.hashDomain(policyDomain),
      digest: utils._TypedDataEncoder.hash(policyDomain, policyTypes, message),
      signer: policyWallet.address, signature: await policyWallet._signTypedData(policyDomain, policyTypes, message),
    };
    fs.writeFileSync(path.join(__dirname, '../test/vectors', file), JSON.stringify(result, null, 2) + '\n');
  }
}
generate().catch(error => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
