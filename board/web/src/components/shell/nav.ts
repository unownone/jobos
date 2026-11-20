import {
  Bookmark,
  ClipboardList,
  Hexagon,
  Home,
  KeyRound,
  Rows3,
  UserRound,
  Users,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
};

export const NAV: NavItem[] = [
  { href: "/home", label: "Home", icon: Home },
  { href: "/board", label: "Board", icon: ClipboardList },
  { href: "/admin/users", label: "Directory", icon: Users },
  { href: "/admin", label: "Invites", icon: KeyRound },
  { href: "/admin/data", label: "Data", icon: Rows3 },
  { href: "/admin/skills", label: "Skills", icon: Hexagon },
  { href: "/admin/memory", label: "Memory", icon: Bookmark },
  { href: "/onboarding", label: "Candidate", icon: UserRound },
];

const DOCK_HREFS: ReadonlySet<string> = new Set(["/home", "/board", "/admin/users"]);

export const DOCK_NAV: NavItem[] = NAV.filter((item) => DOCK_HREFS.has(item.href));

export const MORE_NAV: NavItem[] = NAV.filter((item) => !DOCK_HREFS.has(item.href));

export function isCurrent(href: string, pathname: string): boolean {
  if (pathname === href) return true;
  if (href === "/admin" && (pathname === "/admin" || pathname === "/admin/invites")) return true;
  return false;
}
