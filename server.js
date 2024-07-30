const express = require('express');
const { exec } = require('child_process');
const path = require('path');
const app = express();
app.use(express.json());

app.post('/api/scrape-search', (req, res) => {
  const { keyword, numPosts, downloadPath } = req.body;
  console.log(`Received search request: ${keyword}, ${numPosts}, ${downloadPath}`);
  const scriptPath = path.join('/Users/yz/Desktop/spider', 'xhs_search.py');
  const script = `python ${scriptPath} "${keyword}" ${numPosts} "${downloadPath}"`;
  exec(script, (error, stdout, stderr) => {
    if (error) {
      console.error(`Error executing script: ${stderr}`);
      res.status(500).json({ logs: [error.message] });
      return;
    }
    const logs = stdout.split('\n');
    res.json({ logs, posts: [] });
  });
});

app.post('/api/scrape-profile', (req, res) => {
  const { profileUrls, downloadPath } = req.body;
  console.log(`Received profile request: ${profileUrls}, ${downloadPath}`);
  const scriptPath = path.join('/Users/yz/Desktop/spider', 'xhs_profile.py');
  const script = `python ${scriptPath} "${downloadPath}" ${profileUrls.map(url => `"${url}"`).join(' ')}`;
  exec(script, (error, stdout, stderr) => {
    if (error) {
      console.error(`Error executing script: ${stderr}`);
      res.status(500).json({ logs: [error.message] });
      return;
    }
    const logs = stdout.split('\n');
    res.json({ logs, posts: [] });
  });
});

app.listen(5000, () => console.log('Server running on port 5000'));
