"use client";

import { useState } from "react";
import toast from "react-hot-toast";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { Download, Package, Power, PowerOff, Trash2 } from "lucide-react";
import { Badge, Button, Card, Empty, Input } from "@/components/ui";
import { api } from "@/lib/api";

export default function MarketplacePage() {
  const qc = useQueryClient();
  const [installName, setInstallName] = useState("");

  const installed = useQuery({
    queryKey: ["marketplace", "installed"],
    queryFn: () => api.marketplace.installed(),
  });

  const runnerSkills = useQuery({
    queryKey: ["marketplace", "runner"],
    queryFn: () => api.marketplace.runnerSkills(),
  });

  const installMut = useMutation({
    mutationFn: (pkg: string) => api.marketplace.install(pkg),
    onSuccess: (res) => {
      toast.success(`Installed ${res.data.name} (${res.data.pkg_type})`);
      qc.invalidateQueries({ queryKey: ["marketplace"] });
      setInstallName("");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const uninstallMut = useMutation({
    mutationFn: (pkg: string) => api.marketplace.uninstall(pkg),
    onSuccess: () => {
      toast.success("Uninstalled");
      qc.invalidateQueries({ queryKey: ["marketplace"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const toggleMut = useMutation({
    mutationFn: ({ pkg, enabled }: { pkg: string; enabled: boolean }) =>
      api.marketplace.toggle(pkg, enabled),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["marketplace"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  function handleInstall() {
    const name = installName.trim();
    if (!name) return;
    installMut.mutate(name);
  }

  return (
    <>
      <h1 className="text-2xl font-bold mb-6">Marketplace</h1>

      {/* Install bar */}
      <Card className="mb-6">
        <div className="flex gap-3 items-end">
          <div className="flex-1">
            <label className="text-xs font-medium text-muted block mb-1">
              Install npm package
            </label>
            <Input
              value={installName}
              onChange={(e) => setInstallName(e.target.value)}
              placeholder="e.g. @orchid/skill-web-research or any-npm-package"
              onKeyDown={(e) => e.key === "Enter" && handleInstall()}
            />
          </div>
          <Button
            onClick={handleInstall}
            disabled={!installName.trim() || installMut.isPending}
          >
            <Download size={14} className="mr-1.5" />
            {installMut.isPending ? "Installing…" : "Install"}
          </Button>
        </div>
        <p className="text-xs text-muted mt-2">
          Packages must have a SKILL.md at root with an execute.py entry point. Invalid packages are rejected automatically.
        </p>
      </Card>

      {/* Installed packages */}
      <h2 className="font-semibold mb-3">Installed packages</h2>
      {installed.isLoading && <p className="text-sm text-muted">Loading…</p>}
      {installed.data?.data.length === 0 && <Empty message="No packages installed yet." />}

      <div className="grid gap-2 mb-8">
        {installed.data?.data.map((pkg) => (
          <Card key={pkg.id} className="flex items-center justify-between">
            <div className="flex items-center gap-3 min-w-0">
              <Package size={18} className="text-accent shrink-0" />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{pkg.registered_name}</span>
                  <Badge value={pkg.pkg_type} />
                  {!pkg.enabled && <Badge value="disabled" />}
                </div>
                <p className="text-xs mt-0.5">
                  <span className="text-muted">Use as: </span>
                  <strong className="font-semibold text-foreground font-mono">{pkg.npm_name}</strong>
                </p>
                <p className="text-xs text-muted truncate">
                  {pkg.npm_name} @ {pkg.version}
                </p>
                {pkg.description && (
                  <p className="text-xs text-muted mt-0.5">{pkg.description}</p>
                )}
              </div>
            </div>
            <div className="flex gap-1 shrink-0 ml-4">
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  toggleMut.mutate({ pkg: pkg.npm_name, enabled: !pkg.enabled })
                }
                title={pkg.enabled ? "Disable" : "Enable"}
              >
                {pkg.enabled ? (
                  <PowerOff size={14} className="text-warning" />
                ) : (
                  <Power size={14} className="text-success" />
                )}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  if (confirm(`Uninstall ${pkg.npm_name}?`))
                    uninstallMut.mutate(pkg.npm_name);
                }}
              >
                <Trash2 size={14} className="text-danger" />
              </Button>
            </div>
          </Card>
        ))}
      </div>

      {/* Runner status */}
      <h2 className="font-semibold mb-3">Skill Runner (sandbox)</h2>
      <Card>
        {runnerSkills.isLoading && <p className="text-sm text-muted">Loading…</p>}
        {runnerSkills.error && (
          <p className="text-sm text-danger">Skill runner is not reachable.</p>
        )}
        {runnerSkills.data?.data.length === 0 && (
          <p className="text-sm text-muted">No skills loaded in the sandbox.</p>
        )}
        <div className="space-y-2">
          {runnerSkills.data?.data.map((s) => (
            <div key={s.name} className="flex items-center gap-2 text-sm">
              <Badge value={s.pkg_type} />
              <span className="font-medium">{s.name}</span>
              <span className="text-xs text-muted">{s.description}</span>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
