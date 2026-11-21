export type SessionLine = {
  display_name?: string;
  actor?: string;
  role?: string;
  track?: string | null;
  kind?: string;
  user?: { display_name?: string };
};

export function sessionLine(me: SessionLine): string {
  const name = me.user?.display_name?.trim() || me.display_name?.trim() || me.actor?.trim() || me.role?.trim() || "signed in";
  const lane = me.track?.trim() || me.kind?.trim() || "";
  if (!lane || lane === name) return name;
  return `${name} · ${lane}`;
}
