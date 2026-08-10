import { redirect } from "next/navigation";

// RepoOperator is a local-first tool: `repo up` opens localhost:3000 on the
// user's own machine, so the marketing landing was an extra click between the
// user and their workspace. Product framing lives on npm/GitHub instead — the
// root now goes straight to the app.
export default function HomePage() {
  redirect("/app");
}
