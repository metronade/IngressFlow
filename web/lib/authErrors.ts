// fastapi-users returns machine-readable codes (e.g. "LOGIN_BAD_CREDENTIALS")
// as the error detail, not a human-readable message — map the common ones.
const MESSAGES: Record<string, string> = {
  LOGIN_BAD_CREDENTIALS: "Incorrect email or password.",
  LOGIN_USER_NOT_VERIFIED: "Please verify your email before logging in.",
  REGISTER_USER_ALREADY_EXISTS: "An account with that email already exists.",
  REGISTER_INVALID_PASSWORD: "That password isn't allowed — try a longer or different one.",
};

export function friendlyAuthError(message: string): string {
  return MESSAGES[message] ?? message;
}
