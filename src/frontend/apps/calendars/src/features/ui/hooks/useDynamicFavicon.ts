import { useEffect, useState } from "react";

const FAVICON_SIZE = 64;
// TODO: This path and the app icon/logo paths in DynamicCalendarLogo should
// ideally come from the cunningham theme tokens (e.g.
// themeTokens.components["logo-icon"].src) so they adapt automatically to the
// active theme. Currently the cunningham config doesn't map these assets, so
// this would require extending the theme schema and making these hooks
// theme-aware.
const ICON_PATH = "/cal_icon_no_number.svg";

function generateFaviconDataUrl(day: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const canvas = document.createElement("canvas");
    canvas.width = FAVICON_SIZE;
    canvas.height = FAVICON_SIZE;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      reject(new Error("Canvas 2D context not available"));
      return;
    }

    const img = new Image();
    img.src = ICON_PATH;

    img.onload = () => {
      ctx.drawImage(img, 0, 0, FAVICON_SIZE, FAVICON_SIZE);

      const text = String(day);
      const fontSize = day >= 10 ? 26 : 28;
      ctx.font = `bold ${fontSize}px system-ui, -apple-system, sans-serif`;
      ctx.fillStyle = "rgba(247, 248, 248, 0.95)";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(text, FAVICON_SIZE / 2, FAVICON_SIZE * 0.6);

      resolve(canvas.toDataURL("image/png"));
    };

    img.onerror = () => reject(new Error("Failed to load favicon icon"));
  });
}

/**
 * Returns a data URL for a favicon with the current day of month,
 * or null while generating. Use this in the Next.js <Head> link tag
 * so React manages the DOM and doesn't overwrite it.
 */
export function useDynamicFavicon(): string | null {
  const [faviconUrl, setFaviconUrl] = useState<string | null>(null);

  useEffect(() => {
    const day = new Date().getDate();
    generateFaviconDataUrl(day).then(setFaviconUrl);
  }, []);

  return faviconUrl;
}
