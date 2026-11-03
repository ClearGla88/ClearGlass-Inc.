/* Public analytics destination configuration.

   This file contains identifiers and routes that are public by design. Never
   place API secrets, Stripe keys, personal data or private CRM credentials here.
   Keep provider="queue" until a destination and its privacy controls are
   verified. See docs/ANALYTICS.md for activation and validation steps. */
window.CG_ANALYTICS_CONFIG = Object.freeze({
  provider: "queue",
  measurementId: "",
  domain: "www.clearglassinc.com",
  endpoint: ""
});
