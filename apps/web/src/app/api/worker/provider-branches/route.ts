import { GET as getProviderBranches } from "@/app/api/worker/provider/branches/route";

export async function GET(request: Request) {
  return getProviderBranches(request);
}
