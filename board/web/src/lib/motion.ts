import { useReducedMotion } from "framer-motion";

export const pageMotion = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -6 },
};

export function usePageTransition() {
  const reduce = useReducedMotion();
  if (reduce) return { duration: 0 };
  return { duration: 0.18, ease: [0.2, 0.8, 0.2, 1] as const };
}
