(() => {
  const rail = document.getElementById("loop-rail");
  if (!rail || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return;
  }
  const mark = () => {
    rail.classList.add("is-live");
  };
  if (!("IntersectionObserver" in window)) {
    mark();
    return;
  }
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          mark();
          observer.disconnect();
          return;
        }
      }
    },
    { threshold: 0.35 },
  );
  observer.observe(rail);
})();
