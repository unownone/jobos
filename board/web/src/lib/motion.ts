import { useReducedMotion } from "framer-motion";

export const pageMotion = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -6 },
};

export function pageVariants(reduce: boolean) {
  if (reduce) {
    return {
      initial: false as const,
      animate: { opacity: 1 },
      exit: { opacity: 0 },
    };
  }
  return {
    initial: pageMotion.initial,
    animate: pageMotion.animate,
    exit: pageMotion.exit,
  };
}

export function usePageTransition() {
  const reduce = useReducedMotion();
  if (reduce) return { duration: 0 };
  return { duration: 0.18, ease: [0.2, 0.8, 0.2, 1] as const };
}
