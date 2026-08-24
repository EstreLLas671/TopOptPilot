export const matlabLanguageRegistration = {
  id: "matlab",
  extensions: [".m"],
  aliases: ["MATLAB", "matlab"],
};

export const matlabLanguageDefinition = {
  defaultToken: "",
  tokenPostfix: ".matlab",
  keywords: [
    "break", "case", "catch", "classdef", "continue", "else", "elseif", "end",
    "enumeration", "events", "for", "function", "global", "if", "methods",
    "otherwise", "parfor", "persistent", "properties", "return", "spmd", "switch",
    "try", "while",
  ],
  operators: ["+", "-", "*", "/", "\\", "^", ".*", "./", ".\\", ".^", "<", "<=", ">", ">=", "==", "~=", "&", "|", "&&", "||", "~", "="],
  symbols: /[=><!~?:&|+\-*\/\\^.%]+/,
  tokenizer: {
    root: [
      [/%.*$/, "comment"],
      [/'([^']|'')*'/, "string"],
      [/\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[ij]?\b/, "number"],
      [/[a-zA-Z_]\w*/, { cases: { "@keywords": "keyword", "@default": "identifier" } }],
      [/[{}()\[\]]/, "@brackets"],
      [/@symbols/, { cases: { "@operators": "operator", "@default": "" } }],
      [/[,;]/, "delimiter"],
    ],
  },
};
