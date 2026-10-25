import { Link } from "@/components/shared/link";
import { PageHeader } from "@/components/shared/page-header";

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found" description="There is nothing at this address." />
      <Link to="/" className="text-sm text-primary underline-offset-4 hover:underline">
        Back to the overview
      </Link>
    </>
  );
}
