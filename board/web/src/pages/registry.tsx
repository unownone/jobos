import type { ComponentType } from "react";

import { BoardPage } from "./BoardPage";
import { DataPage } from "./DataPage";
import { HomePage } from "./HomePage";
import { InvitesPage } from "./InvitesPage";
import { JoinPage } from "./JoinPage";
import { LandingPage } from "./LandingPage";
import { LoginPage } from "./LoginPage";
import { MemoryPage } from "./MemoryPage";
import { OnboardingPage } from "./OnboardingPage";
import { SignupPage } from "./SignupPage";
import { SkillsPage } from "./SkillsPage";
import { StartPage } from "./StartPage";
import { UsersPage } from "./UsersPage";

export const PAGES = {
  landing: LandingPage,
  start: StartPage,
  login: LoginPage,
  signup: SignupPage,
  home: HomePage,
  board: BoardPage,
  invites: InvitesPage,
  data: DataPage,
  users: UsersPage,
  skills: SkillsPage,
  memory: MemoryPage,
  onboarding: OnboardingPage,
  join: JoinPage,
} as const;

export type PageName = keyof typeof PAGES;

export function pageFromName(name: string | undefined): ComponentType {
  if (name && Object.prototype.hasOwnProperty.call(PAGES, name)) {
    return PAGES[name as PageName];
  }
  return LandingPage;
}
