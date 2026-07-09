/** navigator.clipboard only exists in secure contexts (HTTPS or localhost).
 * A plain-HTTP deployment reached by IP/domain (no TLS yet) has it
 * `undefined` — calling it silently did nothing, no error, no feedback.
 * Falls back to the classic textarea+execCommand trick, which still works
 * in an insecure context. Returns whether the copy actually succeeded so
 * the caller can show something honest either way. */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // fall through to the legacy method below
    }
  }

  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(textarea);
    return ok;
  } catch {
    return false;
  }
}
