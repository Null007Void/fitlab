# Five-minute quickstart

You do not need a GPU, a model download, an account or a network connection.
Everything below runs offline on a standard Python install.

## 1. Get the code and check Python (30 seconds)

```powershell
git clone <repository-url> fitlab
cd fitlab
python --version          # 3.11 or newer
```

There are no third-party dependencies. The standard library is enough.

## 2. Check your machine (15 seconds)

```powershell
python -m fitlab_evaluation.cli doctor
```

This prints your host, the source identity and the local model identity, if a
model file is present. It loads nothing and runs nothing.

## 3. Ask what your computer can run (60 seconds)

```powershell
python -m fitlab_evaluation.cli plan hardware_to_workloads --budget-bytes 17179869184 --output-dir my-plan
```

`--budget-bytes` is how much memory you are willing to give the model. This
prints and writes a planning document containing, for the local model:

- the idealized weight payload,
- the compute rate needed for a declared target throughput,
- the conditional bandwidth needed,
- and, importantly, what is **unknown** and why.

Open `my-plan/plan.json`. The `requirements` object gives every value a
status: `CALCULATED`, `ESTIMATED`, `UNKNOWN` or `UNAVAILABLE`, plus the
formula used, the assumptions made and the limitations.

## 4. Ask what a workload needs (60 seconds)

```powershell
python -m fitlab_evaluation.cli plan workload_to_hardware --output-dir my-needs
```

This is the other direction of the same engine. `my-needs/advisory.json`
adds a disclosed memory breakdown for hybrid models whose cache the shared
engine cannot model.

## 5. Produce a Capability Passport (60 seconds)

```powershell
python -m fitlab_evaluation.cli trust --output-dir my-source
python -m fitlab_evaluation.cli passport --trust my-source/trust.json --plan my-plan --output-dir my-passport
```

Open `my-passport/passport.html` in any browser. It is a single self-contained
file: no scripts, no remote fonts, no analytics, no network access. You can
email it, attach it, or archive it.

It answers, in order: what your computer is, what was evaluated, whether the
estimate is constrained, what was actually demonstrated, what failed, what is
unknown, and how to reproduce it.

**If you have not run a genuine measurement, the Passport says so.** Every
measurement reads "Unavailable" and the verdict reads "Not evaluated". That is
the honest state, and it is the state this project has been in so far.

## 6. Run the tests (60 seconds)

```powershell
python -W error -m unittest discover -s tests
```

Expected: `OK`. The suite uses synthetic replies and a local test HTTP
server. It never loads a model.

## Where to go next

- [Installation and reproduction](INSTALL_AND_REPRODUCE.md)
- [What the numbers mean](FORMULAS_AND_LIMITATIONS.md)
- [The live measurement procedure](F5_TURNKEY.md)
- [Troubleshooting](TROUBLESHOOTING.md)
