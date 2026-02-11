import { useEffect, useState } from "react";

const FAVICON_SIZE = 64;

const CALENDAR_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 40 40" fill="none">
<path d="M8.18213 11.5846C8.59434 11.4599 9.03364 11.3924 9.49206 11.3924H30.5085C30.9669 11.3924 31.4062 11.4599 31.8184 11.5846C31.8178 10.391 31.8053 9.77042 31.5608 9.29057C31.3342 8.84582 30.9726 8.48423 30.5279 8.25762C30.0223 8 29.3604 8 28.0366 8H11.9639C10.6402 8 9.97827 8 9.47266 8.25762C9.02792 8.48423 8.66633 8.84582 8.43972 9.29057C8.19522 9.77041 8.18276 10.391 8.18213 11.5846Z" fill="#FBC63A"/>
<path fill-rule="evenodd" clip-rule="evenodd" d="M31.3585 22.7595L32.9244 16.496C33.3174 14.9241 32.1285 13.4014 30.5082 13.4014H9.49178C7.8715 13.4014 6.68261 14.9241 7.07559 16.496L8.64148 22.7595C8.74063 23.1561 8.74063 23.571 8.64148 23.9676L7.07559 30.2312C6.68261 31.8031 7.8715 33.3258 9.49178 33.3258H30.5082C32.1285 33.3258 33.3174 31.8031 32.9244 30.2312L31.3585 23.9676C31.2594 23.571 31.2594 23.1561 31.3585 22.7595Z" fill="#2845C1"/>
</svg>`;

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
    const svgBase64 = btoa(CALENDAR_SVG);
    img.src = `data:image/svg+xml;base64,${svgBase64}`;

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

    img.onerror = () => reject(new Error("Failed to load SVG into Image"));
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
