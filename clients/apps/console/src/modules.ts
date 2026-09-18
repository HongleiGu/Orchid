/**
 * The console's extension point. Every screen is a module; adding a tool to the
 * console means adding one entry here — it then gets a route (#/<id>/...), a
 * nav tab if `nav` is set, and a line on the settings page.
 *
 * A module receives the route segments after its id, so `#/runs/01ABC` renders
 * the runs module with path ["01ABC"].
 */
import type { ComponentType } from "react";

import { Overview } from "./screens/Overview";
import { Runs } from "./screens/Runs";
import { Settings } from "./screens/Settings";
import { Templates } from "./screens/Templates";
import { Vault } from "./screens/Vault";

export interface ConsoleModule {
  id: string;
  title: string;
  icon: string;
  description?: string;
  /** Show in the tab bar. Keep this to ~5 on phones. */
  nav: boolean;
  component: ComponentType<{ path: string[] }>;
}

export const modules: ConsoleModule[] = [
  { id: "overview", title: "Overview", icon: "◎", nav: true, component: Overview,
    description: "Server health, spend, active runs." },
  { id: "templates", title: "Templates", icon: "▤", nav: true, component: Templates,
    description: "Start curated workflows; handles required consent." },
  { id: "runs", title: "Runs", icon: "▶", nav: true, component: Runs,
    description: "Live progress, cancellation, cost by step." },
  { id: "vault", title: "Vault", icon: "▦", nav: true, component: Vault,
    description: "Browse, read and download what runs produced." },
  { id: "settings", title: "Settings", icon: "⚙", nav: true, component: Settings,
    description: "Connection, devices, install as an app." },
];

export const defaultModule = modules[0]!;
