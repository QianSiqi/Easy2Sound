fn main() {
    cc::Build::new()
        .file("openjtalk_stub.c")
        .compile("openjtalk_stub");
    println!("cargo:rerun-if-changed=openjtalk_stub.c");
}
