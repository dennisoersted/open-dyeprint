# Releasing

How I make a new release. Mostly a note to my future self, who will have forgotten.

1. **Bump the version** in `pyproject.toml` and `src/opendyeprint/__init__.py`.
2. **Update `CHANGELOG.md`** with what's new.
3. **Run the tests** (`.venv\Scripts\python -m pytest`) and do one real test print. Yes,
   a real one.
4. **Build** with `build.bat` (close the app first).
5. **Zip it:** zip the whole `dist\OpenDyePrint` folder (the `.exe`, `_internal` and
   `licenses`) and call it `OpenDyePrint-x.y.z-windows.zip`.

   ```powershell
   Compress-Archive dist\OpenDyePrint OpenDyePrint-0.3.0-windows.zip
   ```

6. **Commit and tag:**

   ```bat
   git commit -am "Release 0.3.0"
   git tag v0.3.0
   git push --follow-tags
   ```

7. **Create the release on GitHub:** *Releases → Draft a new release*, choose the tag,
   paste the changelog entry and attach the zip. Then go print something.
