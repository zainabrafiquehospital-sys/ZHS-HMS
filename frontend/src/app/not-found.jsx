export default function NotFound() {
  return (
    <div className="flex h-screen w-full flex-col items-center justify-center gap-2 bg-background text-foreground">
      <h1 className="text-xl font-medium">404</h1>
      <p className="text-sm text-muted-foreground">This page does not exist.</p>
    </div>
  );
}
