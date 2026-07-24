import { redirect } from "next/navigation";

export default function Home() {
  // Enter the workflow at step 1 (upload). Data auto-loads, so a returning user
  // just sees it's ready and steps forward.
  redirect("/steps/data");
}
