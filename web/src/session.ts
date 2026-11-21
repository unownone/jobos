import { useEffect, useState } from "react";
import { api } from "./api";

export type SessionUser = {
  id?: string;
  display_name?: string;
  track?: string;
  kind?: string;
};

export type SessionMe = {
  actor?: string;
  role?: string;
  kind?: string;
  user?: SessionUser;
};

export type SessionState =
  | { status: "loading"; me: null }
  | { status: "in"; me: SessionMe }
  | { status: "out"; me: null };

export function useSession(): SessionState {
  const [state, setState] = useState<SessionState>({ status: "loading", me: null });
  useEffect(() => {
    api<SessionMe>("/api/auth/me")
      .then((me) => setState({ status: "in", me }))
      .catch(() => setState({ status: "out", me: null }));
  }, []);
  return state;
}
