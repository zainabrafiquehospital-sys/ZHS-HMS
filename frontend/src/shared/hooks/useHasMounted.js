import { useEffect, useState } from 'react';

// False on the server-rendered/static HTML and on the very first client
// render, true only once React has hydrated. Forms with credential fields
// gate their submit button on this so a click landing before hydration
// finishes hits a disabled button instead of falling through to a native
// (GET) form submission, which would put the field values in the URL.
export function useHasMounted() {
  const [hasMounted, setHasMounted] = useState(false);

  useEffect(() => {
    setHasMounted(true);
  }, []);

  return hasMounted;
}
