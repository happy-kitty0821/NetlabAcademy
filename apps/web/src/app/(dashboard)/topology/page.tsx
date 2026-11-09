/**
 * /topology — redirect to /labs/workspace.
 *
 * The topology editor lives inside the lab workspace. This page exists
 * so that old bookmarks or links to /topology continue to work.
 */
import { redirect } from "next/navigation";

export default function TopologyPage() {
  redirect("/labs/workspace");
}
