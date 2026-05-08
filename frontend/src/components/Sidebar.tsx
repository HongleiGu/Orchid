"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bot, ListChecks, Play, Settings, Home, Store, DollarSign, FolderOpen, Sparkles, Wrench } from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Dashboard", icon: Home },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/tasks", label: "Tasks", icon: ListChecks },
  { href: "/workflow-maker", label: "Workflow Maker", icon: Sparkles },
  { href: "/skill-writer", label: "Skill Writer", icon: Wrench },
  { href: "/runs", label: "Runs", icon: Play },
  { href: "/vault", label: "Vault", icon: FolderOpen },
  { href: "/marketplace", label: "Marketplace", icon: Store },
  { href: "/budget", label: "Budget", icon: DollarSign },
  { href: "/settings", label: "Settings", icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 shrink-0 border-r border-border bg-card flex flex-col">
      <div className="px-4 py-5 border-b border-border">
        <h1 className="text-lg font-bold tracking-tight">Orchid</h1>
      </div>
      <nav className="flex-1 px-2 py-3 space-y-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
                active
                  ? "bg-accent/10 text-accent font-medium"
                  : "text-muted hover:bg-accent/5 hover:text-foreground"
              )}
            >
              <Icon size={18} />
              {label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
