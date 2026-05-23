import supabase from "@/lib/supabase";

export async function registerUser(
  email: string,
  password: string,
  username: string,
) {
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: { data: { username } },
  });
  return { data, error };
}
export async function loginUser(input: string, password: string) {
  let email = input;

  // if no @ symbol, treat as username
  if (!input.includes("@")) {
    const { data } = await supabase.rpc("get_email_from_username", {
      input_username: input,
    });
    email = data;
  }

  return await supabase.auth.signInWithPassword({ email, password });
}

export async function getMyProfile() {
  const { data, error } = await supabase.rpc("get_my_profile");
  return { data, error };
}
