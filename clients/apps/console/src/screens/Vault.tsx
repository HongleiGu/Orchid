import { useState } from "react";

import { deliver, fmtSize, type DeliveryMethod } from "../download";
import { fmtTime } from "../format";
import { useAsync, useRoute } from "../hooks";
import { Markdown } from "../markdown";
import { useClient } from "../session";
import { Card, Empty, ErrorNote, Loading } from "../ui";

// #/vault  ·  #/vault/<project>  ·  #/vault/<project>/<file>
export function Vault({ path }: { path: string[] }) {
  if (path.length >= 2) return <FileView project={path[0]!} filename={path.slice(1).join("/")} />;
  if (path.length === 1) return <FileList project={path[0]!} />;
  return <ProjectList />;
}

function ProjectList() {
  const client = useClient();
  const [, navigate] = useRoute();
  const projects = useAsync(() => client.vaultProjects(), [client], { pollMs: 30_000 });

  if (projects.loading && !projects.data) return <Loading />;
  return (
    <div className="stack">
      <ErrorNote error={projects.error} onRetry={projects.reload} />
      {projects.data?.length === 0 && <Empty>Nothing saved yet. Finished runs are saved here.</Empty>}
      {projects.data?.map((p) => (
        <button key={p.name} className="card card-button" onClick={() => navigate(`vault/${encodeURIComponent(p.name)}`)}>
          <div className="row between">
            <h2>{p.name}</h2>
            <span className="muted">{p.file_count}</span>
          </div>
          <div className="list-sub">
            {fmtSize(p.total_size)}{p.modified_at ? ` · updated ${fmtTime(p.modified_at)}` : ""}
          </div>
        </button>
      ))}
    </div>
  );
}

function FileList({ project }: { project: string }) {
  const client = useClient();
  const [, navigate] = useRoute();
  const files = useAsync(() => client.vaultFiles(project), [client, project], { pollMs: 30_000 });

  return (
    <div className="stack">
      <button className="link back" onClick={() => navigate("vault")}>← Projects</button>
      <h2 className="sub-title">{project}</h2>
      <ErrorNote error={files.error} onRetry={files.reload} />
      {files.loading && !files.data ? <Loading /> : files.data?.length ? (
        <ul className="list card">
          {files.data.map((f) => (
            <li key={f.name}>
              <button className="list-item"
                onClick={() => navigate(`vault/${encodeURIComponent(project)}/${encodeURIComponent(f.name)}`)}>
                <div className="list-main">
                  <span className="file-name">{f.name}</span>
                </div>
                <div className="list-sub">
                  {fmtTime(f.modified_at)} · {fmtSize(f.size)}{f.is_text ? "" : " · download"}
                </div>
              </button>
            </li>
          ))}
        </ul>
      ) : <Empty>This project has no files.</Empty>}
    </div>
  );
}

function FileView({ project, filename }: { project: string; filename: string }) {
  const client = useClient();
  const [, navigate] = useRoute();
  const meta = useAsync(() => client.vaultFiles(project).then((fs) => fs.find((f) => f.name === filename)), [client, project, filename]);
  const file = meta.data;
  const isText = file?.is_text ?? filename.match(/\.(md|markdown|txt|json|csv|tsv|tex|bib|ya?ml|html?|xml|log)$/i) != null;
  const isMarkdown = /\.(md|markdown)$/i.test(filename);

  const content = useAsync(
    () => (isText ? client.vaultFile(project, filename).then((c) => c.content) : Promise.resolve(null)),
    [client, project, filename, isText],
  );

  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<DeliveryMethod | null>(null);
  const [saveError, setSaveError] = useState<unknown>(null);

  async function save() {
    setSaving(true);
    setSaved(null);
    setSaveError(null);
    try {
      setSaved(await deliver(await client.downloadVaultFile(project, filename)));
    } catch (err) {
      setSaveError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="stack">
      <button className="link back" onClick={() => navigate(`vault/${encodeURIComponent(project)}`)}>← {project}</button>
      <Card
        title={<span className="file-name">{filename}</span>}
        action={
          <button className="secondary" onClick={save} disabled={saving}>
            {saving ? "…" : "Save / Share"}
          </button>
        }
      >
        {saved && <div className="note note-ok">{saved === "downloaded" ? "Downloaded." : saved === "shared" ? "Shared." : "Opened."}</div>}
        <ErrorNote error={saveError} />
        {file && <p className="list-sub">{fmtTime(file.modified_at)} · {fmtSize(file.size)}</p>}
      </Card>

      {isText ? (
        content.loading && content.data == null ? <Loading /> :
        content.error ? <ErrorNote error={content.error} onRetry={content.reload} /> :
        content.data != null ? (
          <Card>
            {isMarkdown ? <Markdown text={content.data} /> : <pre className="result">{content.data}</pre>}
          </Card>
        ) : null
      ) : (
        <Card>
          <Empty>This file type can't be shown here — save it to open it.</Empty>
        </Card>
      )}
    </div>
  );
}
