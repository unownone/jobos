(() => {
  fetch("/api/auth/me", { credentials: "same-origin" }).then((res) => {
    if (!res.ok) return;
    document.querySelectorAll('a[href="/login"]').forEach((anchor) => {
      anchor.setAttribute("href", "/board");
      const text = (anchor.textContent || "").trim();
      if (/^log in/i.test(text) || /create an account/i.test(text)) {
        anchor.textContent = "Open board";
      }
    });
  }).catch(() => {});

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
