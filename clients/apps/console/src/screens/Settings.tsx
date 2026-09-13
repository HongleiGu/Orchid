import { useEffect, useState } from "react";

import { modules } from "../modules";
import { useSession } from "../session";
import { Card } from "../ui";

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
}

export function Settings() {
  const { session, disconnect } = useSession();
  const [installEvent, setInstallEvent] = useState<InstallPromptEvent | null>(null);
  const standalone = window.matchMedia("(display-mode: standalone)").matches;

  useEffect(() => {
    const onPrompt = (e: Event) => {
      e.preventDefault();
      setInstallEvent(e as InstallPromptEvent);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  const key = session?.credentials.apiKey ?? "";

  return (
    <div className="stack">
      <Card title="Connection">
        <dl className="kv">
          <dt>Server</dt><dd>{session?.credentials.baseUrl}</dd>
          <dt>Key</dt><dd className="mono">{key.slice(0, 10)}…</dd>
        </dl>
        <button className="danger" onClick={() => disconnect()}>Disconnect and forget key</button>
      </Card>

      <Card title="Install">
        {standalone ? (
          <p>Running as an installed app.</p>
        ) : installEvent ? (
          <button className="primary" onClick={() => installEvent.prompt()}>Install Orchid Console</button>
        ) : (
          <p className="muted">
            iPhone: Safari → Share → 添加到主屏幕. Android: browser menu → 安装应用 / 添加到主屏幕.
            Desktop Chrome/Edge: the install icon in the address bar.
          </p>
        )}
      </Card>

      <Card title="Modules">
        <ul className="list">
          {modules.map((m) => (
            <li key={m.id} className="list-item static">
              <div className="list-main"><span>{m.icon}</span><span>{m.title}</span></div>
              {m.description && <div className="list-sub">{m.description}</div>}
            </li>
          ))}
        </ul>
      </Card>

      <p className="list-sub center">Orchid Console {__APP_VERSION__}</p>
    </div>
  );
}
