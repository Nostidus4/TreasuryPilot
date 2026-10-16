import { demoScenarioEnabled } from '@/lib/env';

import { demoHandlers, installDemoScenario } from './demo';
import { identityHandlers } from './identity';
import { operationHandlers } from './operations';
import { requestHandlers } from './requests';
import { treasuryHandlers } from './treasury';

/** The recordable demo scenario is opt-in: the default dataset (Northwind) is untouched. */
if (demoScenarioEnabled()) installDemoScenario();

export const handlers = [
  ...(demoScenarioEnabled() ? demoHandlers : []),
  ...identityHandlers,
  ...treasuryHandlers,
  ...requestHandlers,
  ...operationHandlers,
];
