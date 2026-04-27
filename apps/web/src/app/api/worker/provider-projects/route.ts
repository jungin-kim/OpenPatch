import { GET as getProviderProjects } from "@/app/api/worker/provider/projects/route";

export async function GET(request: Request) {
  return getProviderProjects(request);
}
