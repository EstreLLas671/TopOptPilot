import Editor, { loader, type EditorProps } from "@monaco-editor/react";
import * as monaco from "monaco-editor/esm/vs/editor/editor.api";
import "monaco-editor/esm/vs/basic-languages/markdown/markdown.contribution";
import "monaco-editor/esm/vs/language/json/monaco.contribution";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import JsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";
import { matlabLanguageDefinition, matlabLanguageRegistration } from "../matlab-language";

type MonacoWorkerScope = typeof globalThis & {
  MonacoEnvironment?: { getWorker: (_moduleId: string, label: string) => Worker };
};

const scope = globalThis as MonacoWorkerScope;
scope.MonacoEnvironment = {
  getWorker: (_moduleId, label) => label === "json" ? new JsonWorker() : new EditorWorker(),
};

if (!monaco.languages.getLanguages().some(language => language.id === matlabLanguageRegistration.id)) {
  monaco.languages.register(matlabLanguageRegistration);
  monaco.languages.setMonarchTokensProvider(
    matlabLanguageRegistration.id,
    matlabLanguageDefinition as monaco.languages.IMonarchLanguage,
  );
}

loader.config({ monaco: monaco as unknown as typeof import("monaco-editor") });

export default function MonacoCodeEditor(props: EditorProps) {
  const theme = document.documentElement.dataset.theme === "dark" ? "vs-dark" : props.theme;
  return <Editor {...props} theme={theme}/>;
}
