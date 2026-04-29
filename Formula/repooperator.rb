class Repooperator < Formula
  desc "AI-powered repository assistant with local worker and web UI"
  homepage "https://github.com/lukepuplett/repooperator"
  url "https://registry.npmjs.org/repooperator/-/repooperator-0.2.2.tgz"
  # Update sha256 after each release:
  # sha256 "$(curl -sL https://registry.npmjs.org/repooperator/-/repooperator-0.2.2.tgz | shasum -a 256 | awk '{print $1}')"
  sha256 ""
  license "MIT"

  depends_on "node"
  depends_on "python@3.12"
  depends_on "git"

  def install
    # Install the npm package into libexec so it does not pollute the global
    # node_modules, then expose the CLI binary via a thin wrapper that sets
    # REPOOPERATOR_PYTHON so the CLI always finds the Homebrew Python.
    libexec.mkpath
    system "npm", "install", "--prefix", libexec, "--no-save", "repooperator@#{version}"

    python_path = Formula["python@3.12"].opt_bin/"python3.12"

    (bin/"repooperator").write <<~EOS
      #!/bin/sh
      export REPOOPERATOR_PYTHON="#{python_path}"
      exec "#{libexec}/bin/repooperator" "$@"
    EOS
    chmod 0755, bin/"repooperator"
  end

  def caveats
    <<~EOS
      RepoOperator has been installed.

      Run the interactive setup wizard:
        repooperator onboard

      Then start the local services:
        repooperator up

      The local worker uses Python 3.12 provided by Homebrew.
      You can override this with the REPOOPERATOR_PYTHON environment variable.
    EOS
  end

  test do
    assert_match "repooperator", shell_output("#{bin}/repooperator --help 2>&1", 0)
  end
end
