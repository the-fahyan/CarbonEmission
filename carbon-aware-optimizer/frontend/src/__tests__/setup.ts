import "@testing-library/jest-dom/vitest";

// jsdom has no ResizeObserver (Recharts' ResponsiveContainer needs it).
class RO { observe() {} unobserve() {} disconnect() {} }
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;
