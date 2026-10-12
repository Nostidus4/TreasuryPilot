/** The in-memory API (src/mocks) stands in until VITE_API_URL points at a real one. */
export const mockApiEnabled =
  import.meta.env.VITE_API_MOCK !== 'false' && !import.meta.env.VITE_API_URL;

export const isTest = import.meta.env.MODE === 'test';
