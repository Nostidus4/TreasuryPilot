import { identityHandlers } from './identity';
import { operationHandlers } from './operations';
import { requestHandlers } from './requests';
import { treasuryHandlers } from './treasury';

export const handlers = [
  ...identityHandlers,
  ...treasuryHandlers,
  ...requestHandlers,
  ...operationHandlers,
];
