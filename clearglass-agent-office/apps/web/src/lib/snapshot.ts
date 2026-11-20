import { cache } from "react";
import { loadSnapshot } from "./office";

// One snapshot fetch per request, shared by the layout and the page.
export const getSnapshot = cache(loadSnapshot);
