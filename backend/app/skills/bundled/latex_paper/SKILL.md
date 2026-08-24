---
name: latex_paper
description: Save a complete LaTeX paper as a real .tex document in the vault, and compile it to PDF when a LaTeX toolchain (tectonic or pdflatex) is available in the runner. Use to persist a final research paper as compilable LaTeX source rather than markdown.
timeout: 180
parameters:
  type: object
  properties:
    project:
      type: string
      description: "Vault project/folder name (e.g. 'autonomous-research')."
    filename:
      type: string
      description: "Filename without extension; .tex is added automatically."
    tex:
      type: string
      description: "Complete, self-contained LaTeX source (documentclass ... \\end{document})."
    compile:
      type: boolean
      default: false
      description: "If true and a LaTeX toolchain is present, also compile the .tex to a PDF in the project's assets/ folder."
  required: [project, filename, tex]
---

Writes `<vault>/<project>/<filename>.tex`. When `compile` is true and `tectonic`
or `pdflatex` is on PATH, it compiles the document into
`<vault>/<project>/assets/<filename>.pdf` and reports the PDF path; otherwise it
returns the saved `.tex` path with a note that no toolchain was found.
