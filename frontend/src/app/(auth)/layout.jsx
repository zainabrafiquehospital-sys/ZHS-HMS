export default function AuthLayout({ children }) {
  return (
    <div className="flex h-screen w-full items-center justify-center bg-background p-6">
      {children}
    </div>
  );
}
