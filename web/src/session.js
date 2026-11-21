import { useEffect, useState } from "react";
import { api } from "./api.js";

export function useSession() {
  const [state, setState] = useState({ status: "loading", me: null });
  useEffect(() => {
    api("/api/auth/me")
      .then((me) => setState({ status: "in", me }))
      .catch(() => setState({ status: "out", me: null }));
  }, []);
  return state;
}
