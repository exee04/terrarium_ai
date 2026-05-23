import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!;
console.log("supabase.ts loaded!");

if (!supabaseUrl || !supabaseKey) {
  console.error("Supabase env variables are missing!");
} else {
  console.log("Supabase connected successfully!");
}
const supabase = createClient(supabaseUrl, supabaseKey);

export default supabase;
