import { useEffect, useState } from "react";
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
    // The prerender is the first paint. CSS `.hub-enter` fades it in.
    // A Framer `initial` of opacity 0 would leave the document blank until JS.
    initial: false as const,
    animate: pageMotion.animate,
    exit: pageMotion.exit,
  };
}

export function usePageTransition() {
  const reduce = useReducedMotion();
  if (reduce) return { duration: 0 };
  return { duration: 0.18, ease: [0.2, 0.8, 0.2, 1] as const };
}

/** In-page enter. `play` stays false for the prerender so the first paint is not opacity 0. Reduced motion fades only, with no transform. */
export function panelVariants(reduce: boolean, play: boolean) {
  if (!play) {
    return { initial: false as const, animate: { opacity: 1 } };
  }
  if (reduce) {
    return { initial: { opacity: 0 }, animate: { opacity: 1 } };
  }
  return { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 } };
}

export function usePanelPlay() {
  const [play, setPlay] = useState(false);
  useEffect(() => setPlay(true), []);
  return play;
}
