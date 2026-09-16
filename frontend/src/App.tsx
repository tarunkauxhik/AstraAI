import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createBrowserRouter, Link, RouterProvider } from "react-router"

import { Brand } from "@/components/Brand"
import { Button } from "@/components/ui/button"
import { NewRunPage } from "@/routes/NewRunPage"
import { RunPage } from "@/routes/RunPage"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false },
    mutations: { retry: false },
  },
})

function NotFoundPage() {
  return (
    <div className="mx-auto max-w-lg px-4">
      <header className="flex h-14 items-center">
        <Brand />
      </header>
      <main className="pt-20 text-center">
        <h1 className="text-xl font-semibold">Page not found</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          This address doesn't match anything in AstraAi.
        </p>
        <Button asChild className="mt-6">
          <Link to="/">Start a new run</Link>
        </Button>
      </main>
    </div>
  )
}

const router = createBrowserRouter([
  { path: "/", element: <NewRunPage /> },
  { path: "/runs/:runId", element: <RunPage /> },
  { path: "*", element: <NotFoundPage /> },
])

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
