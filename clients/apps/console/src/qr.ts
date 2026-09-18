import QRCode from "qrcode";

/**
 * Render text to a QR data URL. Bundled (qrcode has no runtime network use), so
 * it works under the CSP and offline. Medium error correction survives a phone
 * camera reading a screen at an angle.
 */
export async function qrDataUrl(text: string, size = 240): Promise<string> {
  return QRCode.toDataURL(text, {
    errorCorrectionLevel: "M",
    margin: 1,
    width: size,
    color: { dark: "#0f1115", light: "#ffffff" },
  });
}
