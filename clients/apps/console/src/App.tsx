import { useRoute } from "./hooks";
import { defaultModule, modules } from "./modules";
import { Connect } from "./screens/Connect";
import { SessionProvider, useSession } from "./session";
import { UpdateBanner } from "./UpdateBanner";
import { Loading } from "./ui";

export function App() {
  return (
    <SessionProvider>
      <UpdateBanner />
      <Root />
    </SessionProvider>
  );
}

function Root() {
  const { session, loading } = useSession();
  if (loading) return <main className="content"><Loading /></main>;
  return session ? <Shell /> : <Connect />;
}

function Shell() {
  const [segments, navigate] = useRoute();
  const active = modules.find((m) => m.id === segments[0]) ?? defaultModule;
  const Screen = active.component;

  return (
    <div className="shell">
      <nav className="nav" aria-label="Main">
        <div className="nav-brand">
          <img src="/console/icon.svg" alt="" />
          <span>Orchid</span>
        </div>
        {modules.filter((m) => m.nav).map((m) => (
          <button
            key={m.id}
            className={`nav-item ${m.id === active.id ? "nav-on" : ""}`}
            aria-current={m.id === active.id ? "page" : undefined}
            onClick={() => navigate(m.id)}
          >
            <span className="nav-icon" aria-hidden>{m.icon}</span>
            <span className="nav-label">{m.title}</span>
          </button>
        ))}
      </nav>
      <main className="content">
        <h1 className="page-title">{active.title}</h1>
        <Screen key={active.id} path={segments.slice(1)} />
      </main>
    </div>
  );
}
