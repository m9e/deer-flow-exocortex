/**
 * About markdown content. Inlined to avoid raw-loader dependency
 * (Turbopack cannot resolve raw-loader for .md imports).
 */
export const aboutMarkdown = `# About Kamiwaza Flow

Kamiwaza Flow packages the DeerFlow agent runtime as a Kamiwaza-native App Garden workspace.

It keeps the long-running agent loop, memory, tools, skills, artifacts, and subagents, then wires them into local Kamiwaza models and platform services.

---

## Core Features

* **Kamiwaza Models & Tools**: Local platform models and tools appear directly in the agent workspace.
* **Skills & Tools**: Built-in and extensible skills provide task-specific capabilities.
* **Subagents**: Subagents help split larger tasks into scoped pieces of work.
* **Sandbox & File System**: Safely execute code and manipulate files in the sandbox.
* **Context Engineering**: Isolated sub-agent context, summarization to keep the context window sharp.
* **Long-Term Memory**: Keep recording the user's profile, top of mind, and conversation history.

---

## Upstream

Kamiwaza Flow is based on the open source DeerFlow project: [github.com/bytedance/deer-flow](https://github.com/bytedance/deer-flow)

## Kamiwaza

Visit Kamiwaza: [kamiwaza.ai](https://kamiwaza.ai/)

## Support

Join us on Discord: [discord.com/invite/cVGBS5rD2U](https://discord.com/invite/cVGBS5rD2U)

Commercial support: [kamiwaza.ai/support](https://www.kamiwaza.ai/support)

---

## License

DeerFlow is open source and distributed under the **MIT License**.

---

## Acknowledgments

Kamiwaza Flow builds on substantial open source work from the DeerFlow community and the projects below.

### Core Frameworks
- **[LangChain](https://github.com/langchain-ai/langchain)**: A phenomenal framework that powers our LLM interactions and chains.
- **[LangGraph](https://github.com/langchain-ai/langgraph)**: Enabling sophisticated multi-agent orchestration.
- **[Next.js](https://nextjs.org/)**: A cutting-edge framework for building web applications.

### UI Libraries
- **[Shadcn](https://ui.shadcn.com/)**: Minimalistic components that power our UI.
- **[SToneX](https://github.com/stonexer)**: For his invaluable contribution to token-by-token visual effects.

These projects form the backbone of the app.

### Special Thanks
Special thanks to the core authors of DeerFlow 1.0 and 2.0:

- **[Daniel Walnut](https://github.com/hetaoBackend/)**
- **[Henry Li](https://github.com/magiccube/)**

Without their work, this Kamiwaza-native version would not exist.
`;
