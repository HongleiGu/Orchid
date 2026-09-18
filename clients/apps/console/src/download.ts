import type { DownloadedFile } from "@orchid/client-core";

/**
 * Save or share a fetched file. There is no single way that works everywhere,
 * because the file was fetched with an Authorization header — a plain
 * `<a download>` cannot carry that, so we already hold the bytes as a blob and
 * have to hand them to the OS ourselves.
 *
 *   phones   Web Share with files → the native share sheet (Files, WeChat, AirDrop)
 *   desktop  an object-URL anchor click → the browser's download
 *
 * Returns how it was delivered, so the caller can word the confirmation right
 * ("Shared" vs "Downloaded") or fall back to opening the file in a tab.
 */
export type DeliveryMethod = "shared" | "downloaded" | "opened";

export async function deliver(file: DownloadedFile): Promise<DeliveryMethod> {
  const native = new File([file.blob], file.filename, { type: file.mediaType });

  // Prefer the share sheet where the platform can actually share a file. iOS and
  // Android both support this in a home-screen PWA; canShare gates on the file.
  const nav = navigator as Navigator & { canShare?: (d: unknown) => boolean };
  if (typeof navigator.share === "function" && nav.canShare?.({ files: [native] })) {
    try {
      await navigator.share({ files: [native], title: file.filename });
      return "shared";
    } catch (error) {
      // A user cancelling the sheet throws AbortError — not a failure, and not a
      // reason to then also trigger a download they did not ask for.
      if (error instanceof DOMException && error.name === "AbortError") return "shared";
      // Anything else (share unsupported for this type): fall through to save.
    }
  }

  const url = URL.createObjectURL(file.blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = file.filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
    return "downloaded";
  } finally {
    // Revoke after the click has been dispatched, not before.
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  }
}

export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
