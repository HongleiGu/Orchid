"use client";

import Markdown from "react-markdown";
import { cn } from "@/lib/utils";

/**
 * Rich content block types returned by tools/agents.
 *
 * Convention: if the string is valid JSON with a `type` field, render as rich
 * content. Otherwise treat as markdown text.
 *
 * Supported types:
 *   text / markdown  — rendered as GitHub-flavored markdown
 *   image            — <img> with optional alt text
 *   audio            — <audio> player
 *   video            — <video> player
 *   file             — download link
 *   multi            — array of parts, each rendered recursively
 */

interface TextBlock {
  type: "text" | "markdown";
  content: string;
}

interface ImageBlock {
  type: "image";
  url: string;
  alt?: string;
  width?: number;
  height?: number;
}

interface AudioBlock {
  type: "audio";
  url: string;
  format?: string;
}

interface VideoBlock {
  type: "video";
  url: string;
  format?: string;
  poster?: string;
}

interface FileBlock {
  type: "file";
  url: string;
  filename: string;
  size?: number;
}

interface MultiBlock {
  type: "multi";
  parts: ContentBlock[];
}

type ContentBlock = TextBlock | ImageBlock | AudioBlock | VideoBlock | FileBlock | MultiBlock;

// ── Public API ───────────────────────────────────────────────────────────────

export function ContentRenderer({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  const block = parseContent(content);
  return (
    <div className={cn("content-renderer", className)}>
      <BlockRenderer block={block} />
    </div>
  );
}

// ── Parser ───────────────────────────────────────────────────────────────────

function parseContent(raw: string): ContentBlock {
  const trimmed = raw.trim();

  // Try JSON parse
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed && typeof parsed === "object" && "type" in parsed) {
        return parsed as ContentBlock;
      }
    } catch {
      // Not valid JSON — fall through to markdown
    }
  }

  return { type: "markdown", content: raw };
}

// ── Block renderers ──────────────────────────────────────────────────────────

function BlockRenderer({ block }: { block: ContentBlock }) {
  switch (block.type) {
    case "text":
    case "markdown":
      return <MarkdownBlock content={block.content} />;
    case "image":
      return <ImageBlockView block={block} />;
    case "audio":
      return <AudioBlockView block={block} />;
    case "video":
      return <VideoBlockView block={block} />;
    case "file":
      return <FileBlockView block={block} />;
    case "multi":
      return <MultiBlockView block={block} />;
    default:
      // Unknown type — render as raw text
      return <pre className="text-xs whitespace-pre-wrap">{JSON.stringify(block, null, 2)}</pre>;
  }
}

function MarkdownBlock({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none text-foreground prose-headings:text-foreground prose-a:text-accent prose-code:text-sm prose-code:bg-background prose-code:px-1 prose-code:rounded">
      <Markdown>{content}</Markdown>
    </div>
  );
}

function ImageBlockView({ block }: { block: ImageBlock }) {
  return (
    <figure className="my-2">
      <img
        src={block.url}
        alt={block.alt ?? "Generated image"}
        width={block.width}
        height={block.height}
        className="rounded-lg max-w-full max-h-96 object-contain border border-border"
        loading="lazy"
      />
      {block.alt && (
        <figcaption className="text-xs text-muted mt-1">{block.alt}</figcaption>
      )}
    </figure>
  );
}

function AudioBlockView({ block }: { block: AudioBlock }) {
  return (
    <div className="my-2">
      <audio controls className="w-full max-w-md" preload="metadata">
        <source src={block.url} type={block.format ? `audio/${block.format}` : undefined} />
        <a href={block.url} className="text-accent text-sm">Download audio</a>
      </audio>
    </div>
  );
}

function VideoBlockView({ block }: { block: VideoBlock }) {
  return (
    <div className="my-2">
      <video
        controls
        className="rounded-lg max-w-full max-h-96 border border-border"
        poster={block.poster}
        preload="metadata"
      >
        <source src={block.url} type={block.format ? `video/${block.format}` : undefined} />
        <a href={block.url} className="text-accent text-sm">Download video</a>
      </video>
    </div>
  );
}

function FileBlockView({ block }: { block: FileBlock }) {
  const sizeStr = block.size ? ` (${(block.size / 1024).toFixed(1)} KB)` : "";
  return (
    <div className="my-2 flex items-center gap-2 p-2 border border-border rounded-md bg-background">
      <span className="text-sm">📎</span>
      <a href={block.url} download={block.filename} className="text-sm text-accent hover:underline">
        {block.filename}{sizeStr}
      </a>
    </div>
  );
}

function MultiBlockView({ block }: { block: MultiBlock }) {
  return (
    <div className="space-y-2">
      {block.parts.map((part, i) => (
        <BlockRenderer key={i} block={part} />
      ))}
    </div>
  );
}
