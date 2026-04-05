import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format quantity with appropriate precision based on magnitude
 * - Large quantities (>= 100): no decimals
 * - Medium quantities (>= 1): 2 decimals  
 * - Small quantities (>= 0.01): 4 decimals
 * - Tiny quantities (< 0.01): 6 decimals
 */
export function formatQuantity(qty: number | string | null | undefined): string {
  if (qty === null || qty === undefined) return "—";
  const num = typeof qty === "string" ? parseFloat(qty) : qty;
  if (isNaN(num)) return "—";
  
  const abs = Math.abs(num);
  if (abs >= 100) return num.toFixed(2);
  if (abs >= 1) return num.toFixed(3);
  if (abs >= 0.01) return num.toFixed(4);
  if (abs >= 0.0001) return num.toFixed(6);
  return num.toFixed(8);
}

/**
 * Format price with appropriate precision
 * - High prices (>= 1000): 2 decimals
 * - Medium prices (>= 1): 4 decimals  
 * - Low prices (< 1): 6 decimals
 */
export function formatPrice(price: number | string | null | undefined): string {
  if (price === null || price === undefined) return "—";
  const num = typeof price === "string" ? parseFloat(price) : price;
  if (isNaN(num)) return "—";
  
  const abs = Math.abs(num);
  if (abs >= 1000) return `$${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (abs >= 1) return `$${num.toFixed(4)}`;
  return `$${num.toFixed(6)}`;
}

/**
 * Format symbol for display across exchanges and instrument styles.
 * Examples:
 * - "SOL/USDT:USDT" -> "SOL"
 * - "BTC-USDT-SWAP" -> "BTC"
 * - "ETHUSDT" -> "ETH"
 * - "BTC-PERP" -> "BTC"
 */
export function formatSymbolDisplay(symbol: string | null | undefined): string {
  if (!symbol) return "—";
  let s = String(symbol).trim();

  // CCXT style "BASE/QUOTE:SETTLE"
  const ccxtMatch = s.match(/^([^/]+)\/([^:]+)(?::(.+))?$/);
  if (ccxtMatch) {
    return ccxtMatch[1] || s;
  }

  // Normalize common suffixes
  s = s
    .replace(/-USDT-SWAP$/i, "USDT")
    .replace(/-USDC-SWAP$/i, "USDC")
    .replace(/-SWAP$/i, "")
    .replace(/-PERP$/i, "")
    .replace(/-USDT$/i, "USDT")
    .replace(/-USDC$/i, "USDC");

  const quotes = ["USDT", "USDC", "USD", "BUSD"];
  for (const quote of quotes) {
    if (s.toUpperCase().endsWith(quote) && s.length > quote.length) {
      return s.slice(0, -quote.length);
    }
  }

  return s;
}
